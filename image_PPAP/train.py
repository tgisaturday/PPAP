import tensorflow as tf
import numpy as np
from utils.utils import *
from model import *
import sys
import os
import math
import time
from utils.data_helper import data_loader

def xavier_init(size):
    in_dim = size[0]
    xavier_stddev = 1. / tf.sqrt(in_dim / 2.)
    return tf.random_normal(shape=size, stddev=xavier_stddev)

dataset = sys.argv[1]

mb_size, X_dim, width, height, channels,len_x_train, x_train = data_loader(dataset)
    
    
graph = tf.Graph()
with graph.as_default():
    session_conf = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)
    sess = tf.Session(config=session_conf)

    with sess.as_default():
        #input placeholder
        input_shape=[None, width, height, channels]
        filter_sizes=[5, 5, 5, 5, 5]        
        hidden = 128
        z_dim = 128   
        
        if dataset == 'celebA' or dataset == 'lsun':        
            n_filters=[channels, hidden, hidden*2, hidden*4, hidden*8]
        else:      
            n_filters=[channels, hidden, hidden*2, hidden*4]
            
        X = tf.placeholder(tf.float32, shape=[None, width, height,channels])
        A_true_flat = X
        
        #autoencoder variables
        var_G = []
        var_H = []
        #discriminator variables
        W1 = tf.Variable(xavier_init([5,5,channels, hidden//2]))
        W2 = tf.Variable(xavier_init([5,5, hidden//2,hidden]))
        W3 = tf.Variable(xavier_init([5,5,hidden,hidden*2]))
        if dataset == 'celebA' or dataset == 'lsun':
            W4 = tf.Variable(xavier_init([5,5,hidden*2,hidden*4]))
            W5 = tf.Variable(xavier_init([4*4*hidden*4, 1]))
            b5 = tf.Variable(tf.zeros(shape=[1]))
            var_D = [W1,W2,W3,W4,W5,b5] 
        else:
            W4 = tf.Variable(xavier_init([4*4*hidden*2, 1]))
            b4 = tf.Variable(tf.zeros(shape=[1]))
            var_D = [W1,W2,W3,W4,b4] 
        
        global_step = tf.Variable(0, name="global_step", trainable=False)        

        G_sample, A_sample = autoencoder(input_shape, n_filters, filter_sizes,z_dim, A_true_flat, var_G)
        G_hacked, A_hacked = hacker(input_shape, n_filters, filter_sizes,z_dim, G_sample,  A_true_flat, var_H)
             
        D_real_logits = discriminator(A_true_flat, var_D)
        D_fake_logits = discriminator(G_sample, var_D)
        
        gp = gradient_penalty(G_sample, A_true_flat, mb_size,var_D)    
        
        D_loss = tf.reduce_mean(D_fake_logits) - tf.reduce_mean(D_real_logits) +10.0*gp    
        privacy_gain = 0.01*laploss(A_true_flat, G_hacked)
        G_opt_loss = 0.01*laploss(A_true_flat, A_sample)
        H_opt_loss = 0.01*laploss(G_sample, A_hacked)

        G_loss = -tf.reduce_mean(D_fake_logits) - privacy_gain + G_opt_loss 
        H_loss =  privacy_gain + H_opt_loss
        
        tf.summary.image('Original',A_true_flat)
        tf.summary.image('fake',G_sample)
        tf.summary.image('reconstructed_true',A_sample)
        tf.summary.image('decoded_from_fake',G_hacked)
        tf.summary.image('encoded_from_real',A_hacked)        
        tf.summary.scalar('D_loss', D_loss)      
        tf.summary.scalar('G_loss',-tf.reduce_mean(D_fake_logits))     
        tf.summary.scalar('privacy_gain', privacy_gain)
        tf.summary.scalar('G_opt_loss',G_opt_loss)
        tf.summary.scalar('H_opt_loss',G_opt_loss)
        
        merged = tf.summary.merge_all()

        num_batches_per_epoch = int((len_x_train-1)/mb_size) + 1
       
        D_solver = tf.train.AdamOptimizer(learning_rate=1e-4,beta1=0.5, beta2=0.9).minimize(D_loss,var_list=var_D, global_step=global_step)
        G_solver = tf.train.AdamOptimizer(learning_rate=1e-4,beta1=0.5, beta2=0.9).minimize(G_loss,var_list=var_G, global_step=global_step)
        H_solver = tf.train.AdamOptimizer(learning_rate=1e-4,beta1=0.5, beta2=0.9).minimize(H_loss,var_list=var_H, global_step=global_step)
        
        timestamp = str(int(time.time()))
        if not os.path.exists('results/'):
            os.makedirs('results/')        
        out_dir = os.path.abspath(os.path.join(os.path.curdir, "results/models/{}_".format(dataset) + timestamp))
        checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
        checkpoint_prefix = os.path.join(checkpoint_dir, "model")
        if not os.path.exists('results/models/'):
            os.makedirs('results/models/')
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
            saver = tf.train.Saver(tf.global_variables())
        if not os.path.exists('results/dc_out_{}/'.format(dataset)):
            os.makedirs('results/dc_out_{}/'.format(dataset))
        if not os.path.exists('results/generated_{}/'.format(dataset)):
            os.makedirs('results/generated_{}/'.format(dataset))            

        train_writer = tf.summary.FileWriter('results/graphs/{}'.format(dataset),sess.graph)
        sess.run(tf.global_variables_initializer())
        i = 0       
        for it in range(1000000000):
            for _ in range(5):
                if dataset == 'mnist':
                    X_mb, _ = x_train.train.next_batch(mb_size)
                    X_mb = np.reshape(X_mb,[-1,28,28,1])
                else:
                    X_mb = next_batch(mb_size, x_train)
                _, D_loss_curr = sess.run([D_solver, D_loss],feed_dict={X: X_mb})  
            _, H_loss_curr = sess.run([H_solver,H_loss],feed_dict={X: X_mb})     
            summary, _, G_loss_curr = sess.run([merged,G_solver, G_loss],feed_dict={X: X_mb})
            current_step = tf.train.global_step(sess, global_step)
            train_writer.add_summary(summary,current_step)
        
            if it % 100 == 0:
                print('Iter: {}; D_loss: {:.4}; G_loss: {:.4}; H_loss: {:.4};'.format(it,D_loss_curr, G_loss_curr,H_loss_curr))

            if it % 1000 == 0: 
                G_sample_curr,A_sample_curr,re_fake_curr, re_true_curr = sess.run([G_sample,A_sample, G_hacked, A_hacked], feed_dict={X: X_mb})
                samples_flat = tf.reshape(G_sample_curr,[-1,width,height,channels]).eval()
                img_set = np.append(X_mb[:32], samples_flat[:32], axis=0)
                samples_flat = tf.reshape(A_sample_curr,[-1,width,height,channels]).eval() 
                img_set = np.append(img_set, samples_flat[:32], axis=0) 
                samples_flat = tf.reshape(re_fake_curr,[-1,width,height,channels]).eval() 
                img_set = np.append(img_set, samples_flat[:32], axis=0)                 
                samples_flat = tf.reshape(re_true_curr,[-1,width,height,channels]).eval() 
                img_set = np.append(img_set, samples_flat[:32], axis=0) 
                
                fig = plot(img_set, width, height, channels)
                plt.savefig('results/dc_out_{}/{}.png'.format(dataset,str(i).zfill(3)), bbox_inches='tight')
                plt.close(fig)
                i += 1
                path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                print('Saved model at {} at step {}'.format(path, current_step))

            if it% 100000 == 0 and it!=0:
                for ii in range(len_x_train//100):
                    if dataset == 'mnist':
                        Xt_mb, _ = x_train.train.next_batch(100)
                        Xt_mb = np.reshape(Xt_mb,[-1,28,28,1])
                    else:
                        Xt_mb = next_batch(100, x_train)
                    samples = sess.run(G_sample, feed_dict={X: Xt_mb})
                    if ii == 0:
                        generated = samples
                    else:
                        generated = np.concatenate((generated,samples), axis=0)
                np.save('results/generated_{}/generated_image.npy'.format(dataset), generated)

    for iii in range(len_x_train//100):
        xt_mb, _ = mnist.train.next_batch(100,shuffle=False)
        samples = sess.run(G_sample, feed_dict={X: xt_mb})
        if iii == 0:
            generated = samples
        else:
            generated = np.concatenate((generated,samples), axis=0)
    np.save('results/generated_{}/generated_image.npy'.format(dataset), generated)
